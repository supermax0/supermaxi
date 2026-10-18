"""Daily reports must not select yesterday during Baghdad's first three hours."""
from datetime import date, datetime, timedelta

import pytest

from utils import business_time
from utils.daily_report_data import parse_report_date


@pytest.mark.parametrize('hour,minute,expected', [
    (20, 59, date(2026, 10, 18)),
    (21, 0, date(2026, 10, 19)),
    (23, 30, date(2026, 10, 19)),
])
def test_report_default_follows_baghdad_midnight(monkeypatch, hour, minute, expected):
    class Clock(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 10, 18, hour, minute)
    monkeypatch.setattr(business_time, 'datetime', Clock)
    assert business_time.business_today() == expected
    assert parse_report_date(None) == expected
    assert parse_report_date('invalid') == expected
    assert parse_report_date('2026-10-17') == date(2026, 10, 17)


@pytest.mark.parametrize('explicit_date', [None, '2026-10-17'])
def test_daily_session_defaults_to_business_date_and_keeps_explicit_date(daily_app, monkeypatch, explicit_date):
    from extensions import db
    from models.daily_closing import DailySession
    from routes import daily_closing
    from tests.test_daily_closing import _seed

    daily_app.register_blueprint(daily_closing.daily_closing_bp)
    with daily_app.app_context():
        previous, _product, employee = _seed(daily_app)
        previous.status = 'closed'
        db.session.commit()
        employee_id, branch_id = employee.id, previous.branch_id
    monkeypatch.setattr(daily_closing, '_guard', lambda *a, **kw: None)
    monkeypatch.setattr(daily_closing, 'resolve_write_branch_id', lambda *a, **kw: branch_id)
    # Deliberately differ from the machine calendar, even on daytime CI runs.
    business_day = date.today() + timedelta(days=1)
    monkeypatch.setattr(daily_closing, 'business_today', lambda: business_day)
    payload = {'branch_id': branch_id, 'opening_cash': 100_000}
    if explicit_date:
        payload['business_date'] = explicit_date
    client = daily_app.test_client()
    with client.session_transaction() as values:
        values.update(user_id=employee_id, role='admin', tenant_slug='tenant-a')
    response = client.post('/reports/daily-closing/start', json=payload)
    assert response.status_code == 200, response.get_json()
    with daily_app.app_context():
        row = db.session.get(DailySession, response.get_json()['session_id'])
        expected = date.fromisoformat(explicit_date) if explicit_date else business_day
        assert row.business_date == expected


from tests.test_daily_closing import daily_app  # noqa: E402,F401
