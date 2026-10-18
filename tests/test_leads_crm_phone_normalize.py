"""Phone normalization tests for Leads CRM."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.leads_crm.phone_normalize import normalize_iraq_phone, phone_lookup_key, phone_display


def test_normalize_variants():
    assert normalize_iraq_phone("07701234567") == "9647701234567"
    assert normalize_iraq_phone("+9647701234567") == "9647701234567"
    assert normalize_iraq_phone("009647701234567") == "9647701234567"
    assert normalize_iraq_phone("9647701234567") == "9647701234567"
    assert normalize_iraq_phone("7701234567") == "9647701234567"
    assert normalize_iraq_phone("0770 123 4567") == "9647701234567"
    assert normalize_iraq_phone("0770-123-4567") == "9647701234567"


def test_lookup_key():
    assert phone_lookup_key("9647701234567") == "7701234567"


def test_display():
    assert phone_display("9647701234567") == "07701234567"


def test_invalid_phone():
    assert normalize_iraq_phone("") is None
    assert normalize_iraq_phone("123") is None
