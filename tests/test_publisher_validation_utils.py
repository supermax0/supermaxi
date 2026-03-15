from flask import Flask

from modules.publisher.api.validation_utils import parse_pagination, parse_publish_time_utc


def test_parse_pagination_defaults():
    app = Flask(__name__)
    with app.test_request_context("/publisher/api/posts"):
        page, per_page = parse_pagination(default_per_page=20, max_per_page=200)
    assert page == 1
    assert per_page == 20


def test_parse_pagination_bounds():
    app = Flask(__name__)
    with app.test_request_context("/publisher/api/posts?page=-9&per_page=9999"):
        page, per_page = parse_pagination(default_per_page=20, max_per_page=200)
    assert page == 1
    assert per_page == 200


def test_parse_publish_time_utc_from_zulu():
    dt, err = parse_publish_time_utc({"publish_time": "2026-04-01T12:30:00Z"})
    assert err is None
    assert dt is not None
    assert dt.year == 2026
    assert dt.hour == 12
    assert dt.minute == 30


def test_parse_publish_time_utc_from_local_with_offset():
    payload = {
        "publish_time": "2026-04-01T15:30:00",
        "timezone_offset_minutes": -180,  # UTC+3 local -> UTC = 12:30
    }
    dt, err = parse_publish_time_utc(payload)
    assert err is None
    assert dt is not None
    assert dt.hour == 12
    assert dt.minute == 30
