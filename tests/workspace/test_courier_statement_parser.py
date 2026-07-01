"""Courier statement parser tests — Phase 5."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_parse_row_with_amounts():
    from modules.workspace.services.courier_settlement.courier_statement_parser import CourierStatementParser

    class FakeExtraction:
        def get_tables(self):
            return [{
                "page": 1,
                "index": 0,
                "rows": [["#10248", "محمد علي", "560,000", "10,000"]],
                "headers": [],
            }]

        extracted_text = ""
        text_sample = ""

    result = CourierStatementParser.parse(FakeExtraction())
    assert len(result["rows"]) >= 1
    row = result["rows"][0]
    assert row["normalized_order_number"] == "10248"
    assert row["collected_amount"] == 560000
    assert row["delivery_fee"] == 10000
    print("test_parse_row_with_amounts ok")


def test_ignores_header_rows():
    from modules.workspace.services.courier_settlement.courier_statement_parser import CourierStatementParser

    class FakeExtraction:
        def get_tables(self):
            return [{
                "page": 1,
                "index": 0,
                "headers": ["رقم الطلب", "العميل", "المبلغ المحصل", "أجور التوصيل"],
                "rows": [
                    ["رقم الطلب", "العميل", "المبلغ المحصل", "أجور التوصيل"],
                    ["#10248", "علي", "100,000", "5,000"],
                ],
            }]

        extracted_text = ""
        text_sample = ""

    result = CourierStatementParser.parse(FakeExtraction())
    assert len(result["rows"]) == 1
    print("test_ignores_header_rows ok")


def test_ambiguous_row_warning():
    from modules.workspace.services.courier_settlement.courier_statement_parser import CourierStatementParser

    class FakeExtraction:
        def get_tables(self):
            return [{
                "page": 1,
                "index": 0,
                "rows": [["محمد علي", "560,000"]],
                "headers": [],
            }]

        extracted_text = ""
        text_sample = ""

    result = CourierStatementParser.parse(FakeExtraction())
    assert result["rows"]
    assert result["rows"][0].get("warnings") or result.get("warnings")
    print("test_ambiguous_row_warning ok")


if __name__ == "__main__":
    test_parse_row_with_amounts()
    test_ignores_header_rows()
    test_ambiguous_row_warning()
    print("All parser tests passed.")
