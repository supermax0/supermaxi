"""Courier issue detector tests — Phase 5."""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _row(**kwargs):
    defaults = {
        "id": "row1",
        "match_status": "unmatched",
        "normalized_order_number": "10248",
        "collected_amount": 560000,
        "customer_name": "علي",
        "statement_date": None,
        "delivery_fee": 10000,
    }
    defaults.update(kwargs)
    r = SimpleNamespace(**defaults)
    r.get_match_reasons = lambda: []
    r.get_invoice_snapshot = lambda: defaults.get("invoice_snapshot")
    return r


def test_order_not_found_issue():
    from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector

    issues = CourierIssueDetector.detect([_row(match_status="unmatched")], "شركة التوصيل")
    types = {i["issue_type"] for i in issues}
    assert "ORDER_NOT_FOUND" in types
    print("test_order_not_found_issue ok")


def test_duplicate_order_issue():
    from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector

    rows = [
        _row(id="r1", normalized_order_number="10248"),
        _row(id="r2", normalized_order_number="10248", match_status="duplicate"),
    ]
    issues = CourierIssueDetector.detect(rows, "شركة التوصيل")
    assert "DUPLICATE_ORDER_IN_STATEMENT" in {i["issue_type"] for i in issues}
    print("test_duplicate_order_issue ok")


def test_amount_mismatch_issue():
    from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector

    snap = {"id": 10248, "total": 500000, "customer_name": "علي", "status": "تم التسليم", "payment_status": "غير مسدد"}
    rows = [_row(match_status="matched", invoice_snapshot=snap, collected_amount=560000)]
    issues = CourierIssueDetector.detect(rows, "شركة التوصيل")
    assert "AMOUNT_MISMATCH" in {i["issue_type"] for i in issues}
    print("test_amount_mismatch_issue ok")


def test_invalid_order_status_issue():
    from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector

    snap = {"id": 1, "total": 100000, "status": "راجع", "payment_status": "غير مسدد", "customer_name": "x"}
    rows = [_row(match_status="matched", invoice_snapshot=snap)]
    issues = CourierIssueDetector.detect(rows, "شركة التوصيل")
    assert "INVALID_ORDER_STATUS" in {i["issue_type"] for i in issues}
    print("test_invalid_order_status_issue ok")


if __name__ == "__main__":
    test_order_not_found_issue()
    test_duplicate_order_issue()
    test_amount_mismatch_issue()
    test_invalid_order_status_issue()
    print("All issue detector tests passed.")
