"""Classifier tests — Phase 4."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_courier_classification():
    from modules.workspace.services.document_intelligence.document_classifier_service import (
        DocumentClassifierService,
    )

    text = "كشف تسديد شركة التوصيل المبلغ المحصل أجور التوصيل الصافي COD"
    result = DocumentClassifierService.classify(text_sample=text)
    assert result["kind"] == "courier_settlement"
    assert result["confidence"] >= 0.55
    print("test_courier_classification ok")


def test_return_classification():
    from modules.workspace.services.document_intelligence.document_classifier_service import (
        DocumentClassifierService,
    )

    text = "كشف راجع مرتجع سبب الراجع حالة الراجع returned"
    result = DocumentClassifierService.classify(text_sample=text)
    assert result["kind"] == "return_statement"
    assert result["confidence"] >= 0.55
    print("test_return_classification ok")


def test_purchase_classification():
    from modules.workspace.services.document_intelligence.document_classifier_service import (
        DocumentClassifierService,
    )

    text = "فاتورة شراء مورد كمية سعر الوحدة الإجمالي الباركود الموديل"
    result = DocumentClassifierService.classify(text_sample=text)
    assert result["kind"] == "purchase_invoice"
    assert result["confidence"] >= 0.55
    print("test_purchase_classification ok")


def test_low_confidence_unknown():
    from modules.workspace.services.document_intelligence.document_classifier_service import (
        DocumentClassifierService,
    )

    text = "هذا نص عام بدون كلمات مفتاحية خاصة بالمستندات المحاسبية"
    result = DocumentClassifierService.classify(text_sample=text)
    assert result["kind"] == "unknown_document"
    print("test_low_confidence_unknown ok")


if __name__ == "__main__":
    test_courier_classification()
    test_return_classification()
    test_purchase_classification()
    test_low_confidence_unknown()
    print("All classifier tests passed.")
