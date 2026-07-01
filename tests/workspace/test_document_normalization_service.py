"""Normalization service tests — Phase 4."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_arabic_digit_normalization():
    from modules.workspace.services.document_intelligence.document_normalization_service import (
        DocumentNormalizationService,
    )

    amount = DocumentNormalizationService.parse_iqd_amount("٥٦٠،٠٠٠")
    assert amount["valid"] is True
    assert amount["value"] == 560000
    print("test_arabic_digit_normalization ok")


def test_iqd_amount_parsing():
    from modules.workspace.services.document_intelligence.document_normalization_service import (
        DocumentNormalizationService,
    )

    amount = DocumentNormalizationService.parse_iqd_amount("1,250,000 د.ع")
    assert amount["valid"] is True
    assert amount["value"] == 1250000
    print("test_iqd_amount_parsing ok")


def test_order_number_normalization():
    from modules.workspace.services.document_intelligence.document_normalization_service import (
        DocumentNormalizationService,
    )

    order = DocumentNormalizationService.normalize_order_number("#١٠٢٤٨")
    assert order["normalized"] == "10248"
    print("test_order_number_normalization ok")


def test_product_size_normalization():
    from modules.workspace.services.document_intelligence.document_normalization_service import (
        DocumentNormalizationService,
    )

    size = DocumentNormalizationService.normalize_product_size("٥٥ بوصة")
    assert size["valid"] is True
    assert size["size_value"] == 55
    assert size["unit"] == "inch"
    print("test_product_size_normalization ok")


if __name__ == "__main__":
    test_arabic_digit_normalization()
    test_iqd_amount_parsing()
    test_order_number_normalization()
    test_product_size_normalization()
    print("All normalization tests passed.")
