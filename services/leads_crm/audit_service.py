"""Audit logging for Leads CRM."""
from __future__ import annotations

import json
from typing import Any

from extensions import db
from models.core.leads.models import LeadAuditLog


def log_lead_action(
    lead_id: int | None,
    action: str,
    actor_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> LeadAuditLog:
    entry = LeadAuditLog(
        lead_id=lead_id,
        action=action,
        actor_superadmin_id=actor_id,
        details_json=json.dumps(details or {}, ensure_ascii=False),
    )
    db.session.add(entry)
    return entry
