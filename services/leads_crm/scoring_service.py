"""Lead scoring and automation."""
from __future__ import annotations

import json
from typing import Any

from extensions import db
from models.core.leads.models import BusinessLead, LeadAutomationRule, LeadScore


def compute_lead_score(lead: BusinessLead) -> int:
    score = 0
    factors = {}

    if lead.phones:
        score += 20
        factors["has_phone"] = 20

    status_scores = {
        "NEW": 5, "CONTACTED": 15, "REPLIED": 25, "INTERESTED": 40,
        "DEMO_SCHEDULED": 50, "TRIAL": 70, "SUBSCRIBED": 100,
    }
    s = status_scores.get(lead.status, 0)
    score += s
    factors["status"] = s

    if lead.instagram_url or lead.facebook_url:
        score += 10
        factors["social"] = 10

    if lead.full_address:
        score += 5
        factors["address"] = 5

    if lead.next_follow_up_at:
        from datetime import datetime
        if lead.next_follow_up_at < datetime.utcnow():
            score -= 10
            factors["overdue_followup"] = -10

    score = max(0, min(100, score))
    return score, factors


def refresh_lead_score(lead_id: int) -> LeadScore | None:
    lead = BusinessLead.query.get(lead_id)
    if not lead:
        return None

    score, factors = compute_lead_score(lead)
    lead.lead_score = score

    row = LeadScore.query.filter_by(lead_id=lead_id).first()
    if not row:
        row = LeadScore(lead_id=lead_id)
        db.session.add(row)
    row.score = score
    row.factors_json = json.dumps(factors, ensure_ascii=False)
    db.session.commit()
    return row


def refresh_all_scores(limit: int = 500) -> int:
    leads = BusinessLead.query.filter(
        BusinessLead.deleted_at.is_(None),
        BusinessLead.merged_into_lead_id.is_(None),
    ).limit(limit).all()
    count = 0
    for lead in leads:
        refresh_lead_score(lead.id)
        count += 1
    return count


def get_automation_rules() -> list[LeadAutomationRule]:
    return LeadAutomationRule.query.filter_by(is_active=True).all()
