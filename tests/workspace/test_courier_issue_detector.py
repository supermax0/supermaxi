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


def test_partial_payment_matching_remaining_is_informational_not_blocking():
    from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector

    snap = {
        "id": 508,
        "total": 314000,
        "paid_amount": 145000,
        "remaining_amount": 169000,
        "status": "جاري الشحن",
        "payment_status": "جزئي",
        "customer_name": "حسين جواد",
    }
    rows = [_row(
        match_status="matched",
        invoice_snapshot=snap,
        collected_amount=169000,
        delivery_fee=10000,
        net_amount=159000,
    )]
    issues = CourierIssueDetector.detect(rows, "شركة التوصيل")

    assert "AMOUNT_MISMATCH" not in {i["issue_type"] for i in issues}
    partial = next(i for i in issues if i["issue_type"] == "ORDER_PARTIALLY_PAID")
    assert partial["severity"] == "info"
    assert partial["details"]["amount_matches_remaining"] is True


def test_settled_zero_collection_with_delivery_fee_is_not_blocking():
    from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector

    snap = {
        "id": 509,
        "total": 169000,
        "paid_amount": 169000,
        "remaining_amount": 0,
        "status": "تم التوصيل",
        "payment_status": "مسدد",
        "customer_name": "حسين جواد",
        "payment_verified_in_accounts": True,
        "payment_allocations": [
            {"account_name": "الصندوق", "amount": 169000},
        ],
    }
    rows = [_row(
        match_status="matched",
        invoice_snapshot=snap,
        collected_amount=0,
        delivery_fee=10000,
        net_amount=-10000,
    )]
    issues = CourierIssueDetector.detect(rows, "شركة التوصيل")

    assert "AMOUNT_MISMATCH" not in {i["issue_type"] for i in issues}
    settled = next(i for i in issues if i["issue_type"] == "ORDER_ALREADY_SETTLED")
    assert settled["severity"] == "info"
    assert settled["details"]["fee_only_row"] is True
    assert settled["details"]["payment_verified_in_accounts"] is True
    assert "أجور توصيل فقط" in settled["message"]


def test_unpaid_arabic_status_is_not_mistaken_for_settled():
    from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector

    snap = {
        "id": 555,
        "total": 169000,
        "paid_amount": 0,
        "remaining_amount": 169000,
        "status": "جاري الشحن",
        "payment_status": "غير مسدد",
        "customer_name": "جنين",
        "payment_verified_in_accounts": False,
        "payment_allocations": [],
    }
    rows = [_row(
        match_status="matched",
        invoice_snapshot=snap,
        collected_amount=169000,
        delivery_fee=10000,
        net_amount=159000,
    )]

    issues = CourierIssueDetector.detect(rows, "شركة التوصيل")

    assert "ORDER_ALREADY_SETTLED" not in {
        issue["issue_type"] for issue in issues
    }
    assert CourierIssueDetector._is_settled_payment_status("غير مسدد") is False
    assert CourierIssueDetector._is_settled_payment_status("مسدد") is True


def test_settled_verified_collection_posts_delivery_fee_without_duplicate_payment():
    from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector

    snap = {
        "id": 510,
        "total": 169000,
        "paid_amount": 169000,
        "remaining_amount": 0,
        "status": "تم التوصيل",
        "payment_status": "مسدد",
        "customer_name": "حسين جواد",
        "payment_verified_in_accounts": True,
        "payment_allocations": [
            {"account_name": "الصندوق", "amount": 169000},
        ],
    }
    rows = [_row(
        match_status="matched",
        invoice_snapshot=snap,
        collected_amount=169000,
        delivery_fee=10000,
        net_amount=159000,
    )]
    issues = CourierIssueDetector.detect(rows, "شركة التوصيل")

    issue_types = {i["issue_type"] for i in issues}
    assert "AMOUNT_MISMATCH" not in issue_types
    settled = next(i for i in issues if i["issue_type"] == "ORDER_ALREADY_SETTLED")
    assert settled["severity"] == "info"
    assert settled["details"]["prepaid_collection_verified"] is True
    assert settled["details"]["settlement_mode"] == "delivery_fee_only"
    assert "لن يُسجل التحصيل مرة ثانية" in settled["message"]


def test_multi_piece_barcode_allows_partial_piece_collection():
    from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector

    snap = {
        "id": 508,
        "total": 314000,
        "paid_amount": 0,
        "remaining_amount": 314000,
        "shipping_barcodes": ["508", "210605"],
        "status": "جاري الشحن",
        "payment_status": "غير مسدد",
        "customer_name": "حسين جواد",
    }
    rows = [_row(
        normalized_order_number="210605",
        match_status="matched",
        invoice_snapshot=snap,
        collected_amount=169000,
        delivery_fee=10000,
        net_amount=159000,
    )]
    issues = CourierIssueDetector.detect(rows, "شركة التوصيل")

    assert "AMOUNT_MISMATCH" not in {i["issue_type"] for i in issues}
    piece = next(i for i in issues if i["issue_type"] == "PIECE_PARTIAL_SETTLEMENT")
    assert piece["severity"] == "info"
    assert piece["details"]["piece_collected_amount"] == 169000
    assert piece["details"]["remaining_after"] == 145000
    assert piece["details"]["delivery_fee"] == 10000


def test_replacement_note_converts_amount_mismatch_to_planned_warning():
    from modules.workspace.services.courier_settlement.courier_issue_detector import CourierIssueDetector

    snap = {
        "id": 210618,
        "total": 195000,
        "paid_amount": 0,
        "remaining_amount": 195000,
        "shipping_barcodes": ["210618"],
        "note": "تبدل الجهاز إلى موديل آخر",
        "status": "جاري الشحن",
        "payment_status": "غير مسدد",
    }
    issues = CourierIssueDetector.detect([
        _row(
            normalized_order_number="210618",
            match_status="matched",
            invoice_snapshot=snap,
            collected_amount=185000,
            delivery_fee=6000,
            net_amount=179000,
        )
    ], "شركة التوصيل")
    types = {item["issue_type"] for item in issues}
    assert "AMOUNT_MISMATCH" not in types
    planned = next(
        item for item in issues
        if item["issue_type"] == "ORDER_PRICE_ADJUSTMENT_PLANNED"
    )
    assert planned["severity"] == "warning"
    assert planned["details"]["target_status"] == "استبدال"


if __name__ == "__main__":
    test_order_not_found_issue()
    test_duplicate_order_issue()
    test_amount_mismatch_issue()
    test_invalid_order_status_issue()
    print("All issue detector tests passed.")
