"""Courier analysis API tests — Phase 5."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_api_routes_registered():
    from app import app

    rules = [str(r.rule) for r in app.url_map.iter_rules()]
    assert any("courier-analysis/run" in r for r in rules)
    assert any("/courier-analysis/<analysis_id>/rows" in r for r in rules)
    print("test_api_routes_registered ok")


if __name__ == "__main__":
    test_api_routes_registered()
    print("Courier API tests passed.")
