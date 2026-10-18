"""Trial and subscriber conversion service."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from extensions import db
from models.core.leads.models import BusinessLead
from models.core.tenant import Tenant
from services.leads_crm.audit_service import log_lead_action


from services.leads_crm.helpers import actor_superadmin_id as _actor_id


def start_trial_for_lead(
    lead_id: int,
    *,
    company_name: str,
    slug: str,
    trial_days: int = 14,
    plan_key: str = "basic",
) -> tuple[Tenant | None, dict[str, Any]]:
    lead = BusinessLead.query.filter_by(id=lead_id, deleted_at=None).first()
    if not lead:
        return None, {"error": "Lead غير موجود"}
    if lead.finora_company_id:
        tenant = Tenant.query.get(lead.finora_company_id)
        return tenant, {"ok": True, "existing": True}

    base_slug = slug.strip().lower().replace(" ", "-")
    final_slug = base_slug
    i = 2
    while Tenant.query.filter_by(slug=final_slug).first():
        final_slug = f"{base_slug}-{i}"
        i += 1

    tenant = Tenant(
        name=company_name or lead.business_name,
        slug=final_slug,
        db_path=f"tenants/{final_slug}.db",
        is_active=True,
    )
    tenant.subscription_end_date = datetime.utcnow() + timedelta(days=trial_days)
    db.session.add(tenant)
    db.session.flush()

    lead.finora_company_id = tenant.id
    lead.status = "TRIAL"
    lead.trial_started_at = datetime.utcnow()
    lead.trial_ends_at = datetime.utcnow() + timedelta(days=trial_days)

    log_lead_action(lead.id, "trial_started", _actor_id(), {
        "tenant_id": tenant.id,
        "slug": final_slug,
        "trial_days": trial_days,
    })
    db.session.commit()
    return tenant, {"ok": True, "tenant_id": tenant.id, "slug": final_slug}


def convert_to_subscriber(
    lead_id: int,
    *,
    monthly_value: float | None = None,
    plan_key: str | None = None,
) -> tuple[BusinessLead | None, dict[str, Any]]:
    lead = BusinessLead.query.filter_by(id=lead_id, deleted_at=None).first()
    if not lead:
        return None, {"error": "Lead غير موجود"}

    lead.status = "SUBSCRIBED"
    if monthly_value is not None:
        lead.monthly_subscription_value = monthly_value

    if lead.finora_company_id:
        tenant = Tenant.query.get(lead.finora_company_id)
        if tenant:
            tenant.is_active = True

    log_lead_action(lead.id, "converted_subscriber", _actor_id(), {
        "monthly_value": monthly_value,
        "plan_key": plan_key,
    })
    db.session.commit()
    return lead, {"ok": True}


def trials_summary() -> dict[str, Any]:
    now = datetime.utcnow()
    soon = now + timedelta(days=3)

    base = BusinessLead.query.filter(
        BusinessLead.deleted_at.is_(None),
        BusinessLead.merged_into_lead_id.is_(None),
    )

    active = base.filter(BusinessLead.status == "TRIAL").count()
    ending_soon = base.filter(
        BusinessLead.status == "TRIAL",
        BusinessLead.trial_ends_at.isnot(None),
        BusinessLead.trial_ends_at <= soon,
        BusinessLead.trial_ends_at >= now,
    ).count()
    expired = base.filter(
        BusinessLead.status == "TRIAL",
        BusinessLead.trial_ends_at.isnot(None),
        BusinessLead.trial_ends_at < now,
    ).count()
    converted = base.filter(BusinessLead.status == "SUBSCRIBED").count()

    trials = base.filter(BusinessLead.status == "TRIAL").order_by(
        BusinessLead.trial_ends_at.asc()
    ).limit(100).all()

    from services.leads_crm.lead_service import lead_to_dict

    return {
        "counts": {
            "active": active,
            "ending_soon": ending_soon,
            "expired": expired,
            "converted": converted,
        },
        "leads": [lead_to_dict(l) for l in trials],
    }
