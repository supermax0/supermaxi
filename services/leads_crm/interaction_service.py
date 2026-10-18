"""Interaction and timeline service."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from extensions import db
from models.core.leads.models import BusinessLead, LeadInteraction, LeadNote
from services.leads_crm.audit_service import log_lead_action


from services.leads_crm.helpers import actor_superadmin_id as _actor_id


def add_interaction(
    lead_id: int,
    interaction_type: str,
    *,
    result_status: str | None = None,
    note: str | None = None,
    next_follow_up_at: datetime | None = None,
    update_lead_status: str | None = None,
) -> LeadInteraction | None:
    lead = BusinessLead.query.filter_by(id=lead_id, deleted_at=None).first()
    if not lead:
        return None

    interaction = LeadInteraction(
        lead_id=lead_id,
        superadmin_id=_actor_id(),
        interaction_type=interaction_type,
        result_status=result_status,
        note=note,
        contacted_at=datetime.utcnow(),
        next_follow_up_at=next_follow_up_at,
    )
    db.session.add(interaction)

    lead.last_contact_at = datetime.utcnow()
    if next_follow_up_at:
        lead.next_follow_up_at = next_follow_up_at
    if update_lead_status:
        lead.status = update_lead_status
    elif result_status:
        lead.status = result_status

    log_lead_action(lead_id, "interaction_added", _actor_id(), {
        "type": interaction_type,
        "result_status": result_status,
    })
    db.session.commit()
    return interaction


def add_note(lead_id: int, body: str) -> LeadNote | None:
    lead = BusinessLead.query.filter_by(id=lead_id, deleted_at=None).first()
    if not lead or not body.strip():
        return None
    note = LeadNote(lead_id=lead_id, author_superadmin_id=_actor_id(), body=body.strip())
    db.session.add(note)
    log_lead_action(lead_id, "note_added", _actor_id(), {"body": body[:200]})
    db.session.commit()
    return note


def get_timeline(lead_id: int) -> list[dict[str, Any]]:
    items = []
    for i in LeadInteraction.query.filter_by(lead_id=lead_id).order_by(LeadInteraction.contacted_at.desc()).all():
        items.append({
            "kind": "interaction",
            "id": i.id,
            "interaction_type": i.interaction_type,
            "result_status": i.result_status,
            "note": i.note,
            "at": i.contacted_at.isoformat() if i.contacted_at else None,
        })
    for n in LeadNote.query.filter_by(lead_id=lead_id).order_by(LeadNote.created_at.desc()).all():
        items.append({
            "kind": "note",
            "id": n.id,
            "body": n.body,
            "at": n.created_at.isoformat(),
        })
    items.sort(key=lambda x: x.get("at") or "", reverse=True)
    return items
