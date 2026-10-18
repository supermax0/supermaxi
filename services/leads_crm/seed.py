"""Seed default activities and lead statuses."""
from __future__ import annotations

from extensions import db
from models.core.leads.models import BusinessActivity, LeadStatusConfig
from services.leads_crm.constants import DEFAULT_ACTIVITIES, LEAD_STATUSES


def seed_leads_crm_defaults() -> None:
    for idx, (slug, name, name_ar, icon, color) in enumerate(DEFAULT_ACTIVITIES):
        existing = BusinessActivity.query.filter_by(slug=slug).first()
        if existing:
            continue
        db.session.add(
            BusinessActivity(
                slug=slug,
                name=name,
                name_ar=name_ar,
                icon=icon,
                color=color,
                sort_order=idx + 1,
                is_active=True,
            )
        )

    for code, label_ar, sort_order, color in LEAD_STATUSES:
        existing = LeadStatusConfig.query.filter_by(code=code).first()
        if existing:
            continue
        db.session.add(
            LeadStatusConfig(
                code=code,
                label_ar=label_ar,
                sort_order=sort_order,
                color=color,
                is_active=True,
                is_pipeline=code in {
                    "NEW", "CONTACTED", "REPLIED", "INTERESTED",
                    "DEMO_SCHEDULED", "TRIAL", "SUBSCRIBED", "NOT_INTERESTED",
                },
            )
        )

    db.session.commit()
