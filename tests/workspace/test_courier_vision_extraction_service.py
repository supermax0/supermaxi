"""Structured courier vision extraction validation tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _payload():
    return {
        "is_courier_statement": True,
        "company_name": "شركة النقل",
        "statement_date": "2026-07-27",
        "row_count": 2,
        "total_collected_amount": 1010000,
        "total_delivery_fees": 30000,
        "expected_net_amount": 980000,
        "document_warnings": [],
        "rows": [
            {
                "row_index": 1,
                "source_page": 1,
                "order_number": "210793",
                "customer_name": "عميل أول",
                "customer_phone": "07700000001",
                "collected_amount": 520000,
                "delivery_fee": 20000,
                "net_amount": 500000,
                "statement_date": "2026-07-27",
                "confidence": 0.99,
                "warnings": [],
            },
            {
                "row_index": 2,
                "source_page": 1,
                "order_number": "210794",
                "customer_name": "عميل ثاني",
                "customer_phone": "07700000002",
                "collected_amount": 490000,
                "delivery_fee": 10000,
                "net_amount": 480000,
                "statement_date": "2026-07-27",
                "confidence": 0.99,
                "warnings": [],
            },
        ],
    }


def test_exact_totals_are_accepted():
    from modules.workspace.services.document_intelligence.courier_vision_extraction_service import (
        CourierVisionExtractionService,
    )

    validation = CourierVisionExtractionService.validate_payload(_payload())
    assert validation["ok"] is True
    assert validation["blocking"] == []


def test_mismatched_printed_total_blocks_execution():
    from modules.workspace.services.document_intelligence.courier_vision_extraction_service import (
        CourierVisionExtractionService,
    )

    payload = _payload()
    payload["total_delivery_fees"] = 29000
    validation = CourierVisionExtractionService.validate_payload(payload)
    assert validation["ok"] is False
    assert any("total_delivery_fees" in item for item in validation["blocking"])


def test_structured_rows_feed_existing_parser():
    from modules.workspace.services.document_intelligence.courier_vision_extraction_service import (
        CourierVisionExtractionService,
    )
    from modules.workspace.services.courier_settlement.courier_statement_parser import (
        CourierStatementParser,
    )

    extraction_payload = CourierVisionExtractionService._to_extraction_payload(
        _payload(), "test-model"
    )

    class FakeExtraction:
        extracted_text = extraction_payload["text"]
        text_sample = extraction_payload["text_sample"]

        def get_tables(self):
            return extraction_payload["tables"]

    parsed = CourierStatementParser.parse(FakeExtraction())
    assert len(parsed["rows"]) == 2
    assert parsed["rows"][0]["normalized_order_number"] == "210793"
    assert parsed["statement_totals"]["total_delivery_fees"] == 30000
    assert parsed["extraction_method"] == "openai_vision_structured"


if __name__ == "__main__":
    test_exact_totals_are_accepted()
    test_mismatched_printed_total_blocks_execution()
    test_structured_rows_feed_existing_parser()
    print("courier vision extraction tests passed")
