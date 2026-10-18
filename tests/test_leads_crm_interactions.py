"""Interaction and pipeline tests."""
from tests.leads_crm_helpers import get_leads_test_app, unique_phone


def test_interaction_and_pipeline():
    app = get_leads_test_app()
    from extensions import db
    from flask import g, session

    with app.app_context():
        g.tenant = None
        from services.leads_crm.schema import ensure_leads_crm_schema
        from services.leads_crm.seed import seed_leads_crm_defaults
        from models.core.leads.models import BusinessActivity
        from services.leads_crm.lead_service import create_lead
        from services.leads_crm.interaction_service import add_interaction, get_timeline
        from services.leads_crm.pipeline_service import move_lead_status, pipeline_board

        ensure_leads_crm_schema()
        seed_leads_crm_defaults()

        activity = BusinessActivity.query.first()
        lead, _ = create_lead({
            "business_name": "Test Interaction Shop",
            "activity_id": activity.id,
            "phone": unique_phone(),
        }, allow_possible_duplicate=True)
        assert lead is not None

        add_interaction(lead.id, "CALL", result_status="CONTACTED", note="test call")
        timeline = get_timeline(lead.id)
        assert len(timeline) >= 1

        ok, _ = move_lead_status(lead.id, "INTERESTED")
        assert ok

        board = pipeline_board()
        assert "INTERESTED" in board or any("INTERESTED" in k for k in board)
