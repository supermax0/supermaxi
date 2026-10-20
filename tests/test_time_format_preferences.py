"""A tenant clock preference changes presentation, never stored business values."""
from datetime import datetime, time

import pytest

from tests.test_reports_v2 import ctx, TENANT, OTHER_TENANT, _client  # noqa: F401


def test_custom_html_hosts_get_one_clock_bootstrap_but_json_and_fragments_stay_unchanged():
    from flask import Flask, jsonify
    from utils.time_format import install_time_format
    app = Flask("clock-host-test")
    install_time_format(app)
    app.add_url_rule("/custom", "custom", view_func=lambda: "<html><head></head><body>Invoice</body></html>")
    app.add_url_rule("/ready", "ready", view_func=lambda: "<html><head><script>window.FINORA_TIME_CONFIG = {};</script></head></html>")
    app.add_url_rule("/fragment", "fragment", view_func=lambda: "<div>22:00</div>")
    app.add_url_rule("/json", "json", view_func=lambda: jsonify(timestamp="2026-10-21T16:30:00Z"))
    client = app.test_client()
    custom = client.get("/custom").get_data(as_text=True)
    assert custom.count("window.FINORA_TIME_CONFIG") == 1 and '"format": "12"' in custom
    assert 'time-format.js?v=20261021a' in custom
    assert client.get("/ready").get_data(as_text=True).count("window.FINORA_TIME_CONFIG") == 1
    assert client.get("/fragment").get_data(as_text=True) == "<div>22:00</div>"
    assert client.get("/json").get_json() == {"timestamp": "2026-10-21T16:30:00Z"}


def test_legacy_settings_without_ui_flags_do_not_break_pages_or_write_schema(ctx):
    from flask import g
    from sqlalchemy import create_engine, inspect
    from extensions import db
    from extensions_tenant import _tenant_engines
    from models.system_settings import SystemSettings
    from utils.time_format import get_time_format
    tenant = "test_clock_legacy_schema"
    engine = create_engine("sqlite://")
    table = SystemSettings.__tablename__
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
    _tenant_engines[tenant] = engine
    try:
        with ctx["app"].app_context():
            g.tenant = tenant
            assert get_time_format() == "12"
            assert [column["name"] for column in inspect(engine).get_columns(table)] == ["id"]
            db.session.remove()
    finally:
        _tenant_engines.pop(tenant, None)
        engine.dispose()


def test_company_preference_is_shared_but_tenant_isolated(ctx):
    admin = _client(ctx)
    endpoint = "/api/v1/desktop/display-preferences"
    response = admin.post(endpoint, json={"time_format": "24"})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["time_format"] == "24"
    viewer = _client(ctx, key="viewer_id", role="sales")
    assert viewer.get(endpoint).get_json()["time_format"] == "24"
    assert viewer.post(endpoint, json={"time_format": "12"}).status_code == 403
    other = _client(ctx, tenant=OTHER_TENANT, ids=ctx["other"])
    assert other.get(endpoint).get_json()["time_format"] == "12"
    assert admin.get(endpoint).get_json()["time_format"] == "24"


def test_preference_requires_auth_and_valid_format(ctx, monkeypatch):
    endpoint = "/api/v1/desktop/display-preferences"
    with monkeypatch.context() as production:
        production.setenv("FINORA_LOCAL_WORKSPACE", "0")
        anonymous = ctx["app"].test_client()
        assert anonymous.get(endpoint).status_code == 401
        assert anonymous.post(endpoint, json={"time_format": "24"}).status_code == 401
        blocked = anonymous.post("/settings/appearance/update", json={"ui_flags": {"time_format": "24"}})
        assert blocked.status_code in (401, 302)
        if blocked.status_code == 302:
            assert "/login" in blocked.location
    admin = _client(ctx)
    for value in ("25", 24, None, {}, ["12"]):
        assert admin.post(endpoint, json={"time_format": value}).status_code == 400
    assert admin.post("/settings/appearance/update", json={"ui_flags": {"time_format": "invalid"}}).status_code == 400


def test_website_and_native_setting_use_the_same_record(ctx):
    admin = _client(ctx)
    assert admin.post("/settings/appearance/update", json={"ui_flags": {"time_format": "12", "keep_test_flag": True}}).status_code == 200
    assert admin.get("/api/v1/desktop/display-preferences").get_json()["time_format"] == "12"
    assert admin.post("/api/v1/desktop/display-preferences", json={"time_format": "24"}).status_code == 200
    page = admin.get("/settings/appearance")
    assert page.status_code == 200
    assert 'value="24" selected' in page.get_data(as_text=True)
    from flask import g
    from models.system_settings import SystemSettings
    with ctx["app"].app_context():
        g.tenant = TENANT
        assert SystemSettings.get_settings().get_ui_flags()["keep_test_flag"] is True


@pytest.mark.parametrize("mode,stamp,expected", [
    ("12", datetime(2026, 10, 20, 21), "2026-10-21 12:00 ص"),
    ("24", datetime(2026, 10, 20, 21), "2026-10-21 00:00"),
    ("12", datetime(2026, 10, 21, 9), "2026-10-21 12:00 م"),
    ("24", datetime(2026, 10, 21, 16, 30), "2026-10-21 19:30"),
])
def test_rendering_and_exports_obey_the_company_clock(ctx, mode, stamp, expected):
    from flask import g
    from utils.time_format import set_time_format, format_timestamp, format_clock
    from utils.business_time import display_datetime
    from services.reports_export import _display_date
    from extensions import db
    from models.invoice import Invoice
    with ctx["app"].app_context():
        g.tenant = TENANT
        before = [(i.id, i.created_at, i.total, i.paid_amount) for i in Invoice.query.all()]
        set_time_format(mode)
        assert format_timestamp(stamp) == expected
        assert display_datetime(stamp) == expected
        assert _display_date(stamp.isoformat()) == expected
        assert format_clock(time(22)) == ("10:00 م" if mode == "12" else "22:00")
        assert format_timestamp("2026-10-21") == "2026-10-21"
        from modules.finance.routes import _financial_control_print_time
        with_seconds = expected.replace(" ص", ":00 ص").replace(" م", ":00 م") if mode == "12" else expected + ":00"
        assert _financial_control_print_time(stamp.isoformat()) == with_seconds
        assert before == [(i.id, i.created_at, i.total, i.paid_amount) for i in Invoice.query.all()]
        db.session.remove()
