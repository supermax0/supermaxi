"""Trial and subscriber conversion tests."""
from tests.leads_crm_helpers import get_leads_test_app, unique_phone


def test_trial_and_subscribe():
    app = get_leads_test_app()
    from flask import g, session

    with app.app_context():
        g.tenant = None

        from services.leads_crm.schema import ensure_leads_crm_schema
        from services.leads_crm.seed import seed_leads_crm_defaults
        from models.core.leads.models import BusinessActivity
        from services.leads_crm.lead_service import create_lead
        from services.leads_crm.trial_service import start_trial_for_lead, convert_to_subscriber

        ensure_leads_crm_schema()
        seed_leads_crm_defaults()

        activity = BusinessActivity.query.first()
        lead, _ = create_lead({
            "business_name": "Trial Test Co",
            "activity_id": activity.id,
            "phone": unique_phone(),
        }, allow_possible_duplicate=True)
        assert lead is not None

        tenant, resp = start_trial_for_lead(lead.id, company_name="Trial Test Co", slug="trial-test-co")
        assert tenant is not None
        assert resp.get("ok")

        lead2, sub = convert_to_subscriber(lead.id, monthly_value=50000)
        assert lead2.status == "SUBSCRIBED"
        assert float(lead2.monthly_subscription_value) == 50000
