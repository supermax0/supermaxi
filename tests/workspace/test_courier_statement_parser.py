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


def test_parse_orders_export_format():
    from modules.workspace.services.courier_settlement.courier_statement_parser import CourierStatementParser

    class FakeExtraction:
        def get_tables(self):
            return [{
                "page": 1,
                "index": 0,
                "headers": ["#", "باركود شركة النقل", "رقم الهاتف", "اسم الزبون", "المبلغ"],
                "rows": [
                    ["#87", "-", "07754043822", "علي", "560,000"],
                    ["#86", "-", "07710238991", "هند", "45,000"],
                ],
            }]

        extracted_text = ""
        text_sample = ""

    result = CourierStatementParser.parse(FakeExtraction())
    assert len(result["rows"]) == 2
    assert result["rows"][0]["normalized_order_number"] == "87"
    assert result["rows"][0]["customer_phone"] == "07754043822"
    assert result["rows"][0]["collected_amount"] == 560000
    print("test_parse_orders_export_format ok")


def test_phone_number_is_never_counted_as_collected_amount():
    from modules.workspace.services.courier_settlement.courier_statement_parser import CourierStatementParser

    class FakeExtraction:
        def get_tables(self):
            return [{
                "page": 1,
                "index": 0,
                "headers": [
                    "order_number",
                    "customer_name",
                    "customer_phone",
                    "collected_amount",
                    "delivery_fee",
                    "net_amount",
                ],
                "rows": [[
                    "210602",
                    "احمد صالح",
                    "07708857288",
                    7708857288,
                    25000,
                    7708832288,
                ]],
            }]

        extracted_text = ""
        text_sample = ""

    row = CourierStatementParser.parse(FakeExtraction())["rows"][0]
    assert row["customer_phone"] == "07708857288"
    assert row["collected_amount"] is None
    assert row["delivery_fee"] == 25000
    assert row["net_amount"] is None
    assert any("PHONE_MISREAD_AS_AMOUNT" in item for item in row["warnings"])


def test_collected_amount_is_recovered_from_trusted_fee_and_net():
    from modules.workspace.services.courier_settlement.courier_statement_parser import CourierStatementParser

    class FakeExtraction:
        def get_tables(self):
            return [{
                "page": 1,
                "index": 0,
                "headers": [
                    "order_number",
                    "customer_phone",
                    "collected_amount",
                    "delivery_fee",
                    "net_amount",
                ],
                "rows": [[
                    "210602",
                    "07708857288",
                    7708857288,
                    25000,
                    542000,
                ]],
            }]

        extracted_text = ""
        text_sample = ""

    row = CourierStatementParser.parse(FakeExtraction())["rows"][0]
    assert row["collected_amount"] == 567000
    assert row["delivery_fee"] == 25000
    assert row["net_amount"] == 542000
    assert any("PHONE_MISREAD_AS_AMOUNT" in item for item in row["warnings"])


if __name__ == "__main__":
    test_parse_row_with_amounts()
    test_ignores_header_rows()
    test_ambiguous_row_warning()
    test_parse_orders_export_format()
    print("All parser tests passed.")
