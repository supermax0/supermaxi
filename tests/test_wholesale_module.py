"""Smoke tests for wholesale helpers and module wiring."""
from modules.wholesale.services.helpers import (
    next_doc_no,
    normalize_currency,
    to_base_amount,
)


def test_normalize_currency():
    assert normalize_currency("usd") == "USD"
    assert normalize_currency("foo") == "IQD"


def test_to_base_amount_usd():
    assert to_base_amount(10, "USD", 1500) == 15000
    assert to_base_amount(1000, "IQD", 1500) == 1000


def test_next_doc_no_sequence():
    from datetime import date

    today = date.today().strftime("%Y%m%d")
    first = next_doc_no("WS", None)
    assert first.startswith(f"WS-{today}-")
    second = next_doc_no("WS", first)
    assert second.endswith("0002")


def test_wholesale_blueprints_importable():
    from modules.wholesale.api.routes import wholesale_api_bp
    from modules.wholesale.web.routes import wholesale_web_bp

    assert wholesale_api_bp.url_prefix == "/api/wholesale"
    assert wholesale_web_bp.url_prefix == "/wholesale"
