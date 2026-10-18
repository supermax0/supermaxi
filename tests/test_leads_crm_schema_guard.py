"""Regression tests for Leads CRM legacy schema upgrades."""
from __future__ import annotations

from flask import Flask, g
from sqlalchemy import inspect, text

from extensions import db


def _make_app(db_path):
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path.as_posix()}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    db.init_app(app)
    return app


def test_leads_schema_guard_adds_missing_legacy_columns(tmp_path):
    app = _make_app(tmp_path / "legacy_leads.sqlite")

    with app.app_context():
        g.tenant = None
        from services.leads_crm import schema

        schema._SCHEMA_ENSURED = False
        with db.engine.begin() as conn:
            conn.execute(text("CREATE TABLE business_leads (id INTEGER PRIMARY KEY)"))

        schema.ensure_leads_crm_schema()

        inspector = inspect(db.engine)
        lead_columns = {c["name"] for c in inspector.get_columns("business_leads")}
        assert {
            "business_name",
            "normalized_business_name",
            "deleted_at",
            "merged_into_lead_id",
            "source_primary",
            "lead_score",
        }.issubset(lead_columns)

        phone_columns = {c["name"] for c in inspector.get_columns("business_lead_phones")}
        assert {"lead_id", "normalized_phone", "is_primary"}.issubset(phone_columns)

        run_columns = {c["name"] for c in inspector.get_columns("lead_discovery_runs")}
        assert {"status", "requested_limit", "created_count", "settings_json"}.issubset(run_columns)
