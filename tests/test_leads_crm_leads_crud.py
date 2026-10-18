"""Leads CRM CRUD and dedup tests."""
import uuid

from tests.leads_crm_helpers import get_leads_test_app, unique_phone


def _setup_db():
    app = get_leads_test_app()
    from extensions import db
    from flask import g

    with app.app_context():
        g.tenant = None
        from services.leads_crm.schema import ensure_leads_crm_schema
        from services.leads_crm.seed import seed_leads_crm_defaults

        ensure_leads_crm_schema()
        seed_leads_crm_defaults()
        return app, db


def test_create_lead_and_exact_duplicate():
    app, db = _setup_db()
    with app.app_context():
        from flask import g
        g.tenant = None
        from models.core.leads.models import BusinessActivity, BusinessLead
        from services.leads_crm.lead_service import create_lead

        activity = BusinessActivity.query.filter_by(slug="clothing").first()
        assert activity is not None

        phone = unique_phone()
        unique_name = f"زوفا{uuid.uuid4().hex[:12]}"
        lead, resp = create_lead({
            "business_name": unique_name,
            "activity_id": activity.id,
            "phone": phone,
            "governorate": "بغداد",
            "district": "المنصور",
            "status": "INTERESTED",
        })
        assert lead is not None, resp
        assert resp.get("ok")

        lead2, resp2 = create_lead({
            "business_name": f"Other-{uuid.uuid4().hex[:8]}",
            "activity_id": activity.id,
            "phone": f"+964{phone[1:]}",
            "governorate": "بغداد",
        })
        assert lead2 is None
        assert resp2.get("error") == "duplicate_phone"
        assert resp2["duplicate"].level == "EXACT"

        count = BusinessLead.query.filter(BusinessLead.merged_into_lead_id.is_(None)).count()
        assert count >= 1


def test_list_leads_filter():
    app, db = _setup_db()
    with app.app_context():
        from flask import g
        from services.leads_crm.lead_service import list_leads

        g.tenant = None
        result = list_leads(search="444444", governorate="بغداد")
        assert "leads" in result
        assert "total" in result
