"""Export service tests."""
from tests.leads_crm_helpers import get_leads_test_app


def test_export_leads_excel():
    app = get_leads_test_app()
    from flask import g

    with app.app_context():
        g.tenant = None
        from services.leads_crm.schema import ensure_leads_crm_schema
        from services.leads_crm.export_service import export_leads_excel

        ensure_leads_crm_schema()
        xlsx = export_leads_excel()
        assert isinstance(xlsx, bytes)
        assert len(xlsx) > 100
