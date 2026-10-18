"""Reports service tests."""
from tests.leads_crm_helpers import get_leads_test_app


def test_overview_kpis():
    app = get_leads_test_app()
    from flask import g

    with app.app_context():
        g.tenant = None
        from services.leads_crm.schema import ensure_leads_crm_schema
        from services.leads_crm.report_service import overview_kpis, pipeline_funnel

        ensure_leads_crm_schema()
        kpis = overview_kpis()
        assert "total_leads" in kpis
        assert "mrr_from_leads" in kpis
        funnel = pipeline_funnel()
        assert isinstance(funnel, list)
