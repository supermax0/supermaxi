from datetime import datetime, timedelta
from types import SimpleNamespace

from modules.facebook_monitor.formatters import format_duration, format_iqd, parse_date_range
from modules.facebook_monitor.status import classify_message
from modules.facebook_monitor.strength import page_strength_score, score_tone


def test_page_strength_rewards_orders_and_conversion():
    strong = page_strength_score(
        orders=100, max_orders=100, conversion_rate=20, sales=1000, max_sales=1000,
        avg_response_seconds=20, returns=0,
    )
    weak = page_strength_score(
        orders=0, max_orders=100, conversion_rate=0, sales=0, max_sales=1000,
        avg_response_seconds=400, returns=10,
    )
    assert strong > weak
    assert 0 <= strong <= 100
    assert score_tone(strong) == "success"


def test_message_status_sla():
    now = datetime(2026, 9, 25, 12, 0, 0)
    status, seconds = classify_message(received_at=now - timedelta(seconds=20), answered_at=None, now=now)
    assert status == "NEW"
    assert seconds == 20
    status, _ = classify_message(received_at=now - timedelta(seconds=120), answered_at=None, now=now)
    assert status == "WAITING_REPLY"
    status, _ = classify_message(received_at=now - timedelta(seconds=200), answered_at=None, now=now)
    assert status == "LATE"
    status, seconds = classify_message(
        received_at=now - timedelta(seconds=40),
        answered_at=now,
        now=now,
    )
    assert status == "ANSWERED"
    assert seconds == 40
    status, _ = classify_message(
        received_at=now - timedelta(minutes=5),
        answered_at=now,
        now=now,
        has_order=True,
    )
    assert status == "ORDER_CREATED"


def test_formatters():
    assert format_duration(43) == "00:43"
    assert format_duration(None) == "—"
    assert format_iqd(98_400_000, compact=True) == "98.4M د.ع"
    assert format_iqd(420_000) == "420,000 د.ع"
    key, start, end = parse_date_range("today", None, None, datetime(2026, 9, 25, 15, 0, 0))
    assert key == "today"
    # Iraq business day (UTC+3): local midnight converted back to UTC.
    assert start == datetime(2026, 9, 24, 21, 0, 0)
    assert end == datetime(2026, 9, 25, 21, 0, 0)
    all_key, all_start, all_end = parse_date_range("all", None, None, datetime(2026, 9, 25, 15, 0, 0))
    assert all_key == "all"
    assert all_start == datetime(2025, 9, 25, 21, 0, 0)
    assert all_end == datetime(2026, 9, 25, 21, 0, 0)
    default_key, _, _ = parse_date_range(None, None, None, datetime(2026, 9, 25, 15, 0, 0))
    assert default_key == "last_30"


def test_single_enabled_employee_receives_live_message_even_when_cap_is_full(monkeypatch):
    from modules.facebook_routing import engine

    employee = SimpleNamespace(id=14, is_active=True)
    link = SimpleNamespace(employee_id=14, last_assigned_at=None)
    state = SimpleNamespace(accept_messages=True, presence="AVAILABLE")
    query = SimpleNamespace(filter_by=lambda **_kwargs: SimpleNamespace(all=lambda: [link]))

    monkeypatch.setattr(engine, "FacebookPageEmployee", SimpleNamespace(query=query))
    monkeypatch.setattr(
        engine,
        "Employee",
        SimpleNamespace(query=SimpleNamespace(get=lambda _id: employee)),
    )
    monkeypatch.setattr(engine, "can_use_inbox", lambda _employee: True)
    monkeypatch.setattr(engine, "_state", lambda _id: state)
    monkeypatch.setattr(engine, "_employee_cap", lambda _id, page_id=None: 10)
    monkeypatch.setattr(engine, "_active_count", lambda _id, page_id=None: 20)

    routing = SimpleNamespace(routing_enabled=True)
    assert engine.eligible_employees("page-1", routing) == []
    pool = engine.eligible_employees("page-1", routing, allow_single_overflow=True)
    assert [row[0].id for row in pool] == [14]


def test_meta_import_defers_routing_until_recent_messages_are_known():
    from pathlib import Path

    routes_source = Path("modules/ai_sales/routes.py").read_text(encoding="utf-8")
    engine_source = Path("modules/ai_sales/engine.py").read_text(encoding="utf-8")

    assert "route_facebook=False" in routes_source
    assert "has_recent_actionable_inbound" in routes_source
    assert "if route_facebook:" in engine_source


def test_routing_queue_starts_at_iraq_midnight():
    from modules.facebook_routing.engine import routing_day_start

    assert routing_day_start(datetime(2026, 9, 29, 11, 0)) == datetime(2026, 9, 28, 21, 0)
    assert routing_day_start(datetime(2026, 9, 29, 20, 59)) == datetime(2026, 9, 28, 21, 0)
    assert routing_day_start(datetime(2026, 9, 29, 21, 0)) == datetime(2026, 9, 29, 21, 0)


def test_server_runs_meta_inbox_auto_sync():
    from pathlib import Path

    scheduler_source = Path("modules/publisher/services/scheduler_service.py").read_text(encoding="utf-8")
    routes_source = Path("modules/ai_sales/routes.py").read_text(encoding="utf-8")

    assert 'id="meta_inbox_auto_sync"' in scheduler_source
    assert 'os.environ.get("META_INBOX_SYNC_SECONDS", "60")' in scheduler_source
    assert "result = _sync_meta_channels(" in routes_source
    assert "enrich_profiles=False" in routes_source
    assert "drain_unassigned_queue(" in routes_source
    assert '"skipped": True' not in routes_source[routes_source.index("def api_meta_auto_sync"):][:600]
