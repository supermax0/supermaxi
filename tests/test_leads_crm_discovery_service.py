"""Automated map discovery tests."""
from __future__ import annotations

import uuid

from tests.leads_crm_helpers import get_leads_test_app, unique_phone


class _FakeOverpassResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _setup_db():
    app = get_leads_test_app()
    from extensions import db
    from flask import g

    with app.app_context():
        g.tenant = None
        from services.leads_crm import schema
        from services.leads_crm.seed import seed_leads_crm_defaults

        schema._SCHEMA_ENSURED = False
        schema.ensure_leads_crm_schema()
        seed_leads_crm_defaults()
    return app, db


def test_discovery_creates_map_lead_and_skips_source_duplicate(monkeypatch):
    app, db = _setup_db()
    unique_name = f"زونة{uuid.uuid4().hex[:12]}"
    phone = unique_phone()
    osm_id = int(uuid.uuid4().int % 900000000) + 100000
    payload = {
        "elements": [
            {
                "type": "node",
                "id": osm_id,
                "lat": 33.3152,
                "lon": 44.3661,
                "tags": {
                    "name": unique_name,
                    "shop": "clothes",
                    "phone": phone,
                    "addr:city": "بغداد",
                },
            }
        ]
    }

    def fake_post(*args, **kwargs):
        return _FakeOverpassResponse(payload)

    with app.app_context():
        from flask import g
        from models.core.leads.models import BusinessLead, LeadSourceRecord
        from services.leads_crm import discovery_service

        g.tenant = None
        monkeypatch.setattr(discovery_service.requests, "post", fake_post)
        monkeypatch.setattr(discovery_service, "is_ai_enrichment_available", lambda: False)
        result = discovery_service.run_lead_discovery(limit=1, activity_slugs=["clothing"], governorate="بغداد")
        assert result["ok"] is True
        assert result["run"]["created_count"] == 1

        lead = BusinessLead.query.filter_by(business_name=unique_name).first()
        assert lead is not None
        assert lead.latitude == 33.3152
        assert lead.longitude == 44.3661
        assert lead.source_primary == discovery_service.SOURCE_NAME
        source_key = f"osm:node:{osm_id}"
        assert LeadSourceRecord.query.filter_by(source_name=discovery_service.SOURCE_NAME, source_detail=source_key).first()

        result2 = discovery_service.run_lead_discovery(limit=1, activity_slugs=["clothing"], governorate="بغداد")
        assert result2["run"]["created_count"] == 0


def test_discovery_requires_phone_by_default(monkeypatch):
    app, db = _setup_db()
    unique_name = f"لارقم{uuid.uuid4().hex[:12]}"
    osm_id = int(uuid.uuid4().int % 900000000) + 100000
    payload = {
        "elements": [
            {
                "type": "node",
                "id": osm_id,
                "lat": 33.30,
                "lon": 44.39,
                "tags": {
                    "name": unique_name,
                    "shop": "clothes",
                    "addr:city": "بغداد",
                },
            }
        ]
    }

    def fake_post(*args, **kwargs):
        return _FakeOverpassResponse(payload)

    with app.app_context():
        from flask import g
        from models.core.leads.models import BusinessLead
        from services.leads_crm import discovery_service

        g.tenant = None
        monkeypatch.setattr(discovery_service.requests, "post", fake_post)
        monkeypatch.setattr(discovery_service, "is_ai_enrichment_available", lambda: False)
        result = discovery_service.run_lead_discovery(limit=1, activity_slugs=["clothing"], governorate="بغداد")

        assert result["ok"] is True
        assert result["run"]["created_count"] == 0
        assert result["run"]["skipped_count"] >= 1
        assert BusinessLead.query.filter_by(business_name=unique_name).first() is None


def test_map_payload_filters_to_phone_leads_by_default():
    app, db = _setup_db()
    with app.app_context():
        from flask import g
        from models.core.leads.models import BusinessActivity, BusinessLead
        from services.leads_crm.discovery_service import map_leads_payload
        from services.leads_crm.lead_service import create_lead

        g.tenant = None
        activity = BusinessActivity.query.filter_by(slug="clothing").first()
        phone_name = f"هاتف{uuid.uuid4().hex[:12]}"
        no_phone_name = f"بدونهاتف{uuid.uuid4().hex[:12]}"

        lead, response = create_lead({
            "business_name": phone_name,
            "activity_id": activity.id,
            "phone": unique_phone(),
            "latitude": 33.31,
            "longitude": 44.36,
            "governorate": "بغداد",
        })
        assert lead is not None, response
        db.session.add(BusinessLead(
            activity_id=activity.id,
            business_name=no_phone_name,
            normalized_business_name=no_phone_name,
            latitude=33.32,
            longitude=44.37,
            governorate="بغداد",
        ))
        db.session.commit()

        filtered = map_leads_payload(search=phone_name[:3], has_phone=True)
        assert any(item["business_name"] == phone_name for item in filtered["leads"])

        filtered_no_phone = map_leads_payload(search=no_phone_name, has_phone=True)
        assert filtered_no_phone["total"] == 0
