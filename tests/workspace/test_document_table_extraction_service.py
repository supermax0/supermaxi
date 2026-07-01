"""Table extraction tests — Phase 4."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_heuristic_table_from_text():
    from modules.workspace.services.document_intelligence.document_table_extraction_service import (
        DocumentTableExtractionService,
    )

    text = "#10248  محمد علي  560,000  10,000\n#10249  سارة  120,000  5,000"
    result = DocumentTableExtractionService.extract_tables(
        "/tmp/none.pdf", "application/pdf", text
    )
    assert result["status"] in ("completed", "partial")
    assert len(result["tables"]) >= 1
    assert len(result["tables"][0]["rows"]) >= 2
    print("test_heuristic_table_from_text ok")


def test_no_text_returns_not_available():
    from modules.workspace.services.document_intelligence.document_table_extraction_service import (
        DocumentTableExtractionService,
    )

    result = DocumentTableExtractionService.extract_tables(
        "/tmp/none.pdf", "application/pdf", ""
    )
    assert result["status"] == "not_available"
    print("test_no_text_returns_not_available ok")


if __name__ == "__main__":
    test_heuristic_table_from_text()
    test_no_text_returns_not_available()
    print("All table extraction tests passed.")
