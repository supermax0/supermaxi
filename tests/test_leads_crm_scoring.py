"""Lead scoring tests."""
from tests.leads_crm_helpers import get_leads_test_app, unique_phone


def test_scoring():
    app = get_leads_test_app()
    from flask import g

    with app.app_context():
        g.tenant = None
        from services.leads_crm.schema import ensure_leads_crm_schema
        from services.leads_crm.seed import seed_leads_crm_defaults
        from models.core.leads.models import BusinessActivity
        from services.leads_crm.lead_service import create_lead
        from services.leads_crm.scoring_service import refresh_lead_score, compute_lead_score

        ensure_leads_crm_schema()
        seed_leads_crm_defaults()

        activity = BusinessActivity.query.first()
        lead, _ = create_lead({
            "business_name": "Score Test",
            "activity_id": activity.id,
            "phone": unique_phone(),
            "instagram_url": "@test",
        }, allow_possible_duplicate=True)
        assert lead is not None

        from models.core.leads.models import BusinessLead
        lead = BusinessLead.query.get(lead.id)
        score, factors = compute_lead_score(lead)
        assert score > 0
        assert "has_phone" in factors

        row = refresh_lead_score(lead.id)
        assert row.score == score
