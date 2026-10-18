"""Shared Flask app fixture for Leads CRM integration tests."""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TEST_DB = ROOT / "tests" / "_leads_crm_test.sqlite"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB.as_posix()}")


def get_leads_test_app():
    from app import app
    return app


def unique_phone() -> str:
    """Generate a unique Iraqi mobile for isolated test runs."""
    return f"07{random.randint(100000000, 999999999)}"
