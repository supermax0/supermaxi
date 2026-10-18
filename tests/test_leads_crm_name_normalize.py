"""Business name normalization tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.leads_crm.name_normalize import normalize_business_name, name_similarity_score


def test_arabic_normalization():
    assert normalize_business_name("أزياء الملك") == normalize_business_name("ازياء الملك")
    assert normalize_business_name("أزيــــاء   الملك") == normalize_business_name("ازياء الملك")


def test_similarity():
    score = name_similarity_score("أزياء الملك", "ازياء الملك")
    assert score >= 0.95
