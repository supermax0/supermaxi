"""Text extraction tests — Phase 4."""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_pdf_not_available_without_dependency():
    from modules.workspace.services.document_intelligence.document_text_extraction_service import (
        DocumentTextExtractionService,
    )

    with patch.object(
        DocumentTextExtractionService,
        "_extract_pdf",
        return_value=DocumentTextExtractionService._not_available(
            "PDF text extraction dependency not installed"
        ),
    ):
        result = DocumentTextExtractionService.extract_from_file(
            "/tmp/fake.pdf", "application/pdf", "test.pdf"
        )
    assert result["status"] == "not_available"
    print("test_pdf_not_available_without_dependency ok")


def test_mock_pdf_extraction():
    from modules.workspace.services.document_intelligence.document_text_extraction_service import (
        DocumentTextExtractionService,
    )

    mock = {
        "status": "completed",
        "text": "كشف تسديد",
        "text_sample": "كشف تسديد",
        "pages": [{"page": 1, "text": "كشف تسديد", "method": "pdf_text"}],
        "warnings": [],
    }
    with patch.object(DocumentTextExtractionService, "_extract_pdf", return_value=mock):
        result = DocumentTextExtractionService.extract_from_file(
            "/tmp/x.pdf", "application/pdf"
        )
    assert result["status"] == "completed"
    assert "تسديد" in result["text"]
    print("test_mock_pdf_extraction ok")


if __name__ == "__main__":
    test_pdf_not_available_without_dependency()
    test_mock_pdf_extraction()
    print("All text extraction tests passed.")
