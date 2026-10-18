"""Courier order matcher tests — Phase 5."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _invoice(
    id_,
    total,
    name="محمد",
    phone="07701234567",
    phone2=None,
    status="تم التسليم",
    payment="غير مسدد",
    paid_amount=0,
):
    customer = SimpleNamespace(phone=phone, phone2=phone2)
    return SimpleNamespace(
        id=id_,
        customer_name=name,
        customer=customer,
        total=total,
        status=status,
        payment_status=payment,
        paid_amount=paid_amount,
        shipping_company_id=1,
        barcode=None,
        shipping_barcode=None,
        shipping_barcodes_json=None,
        created_at=None,
    )


def test_exact_order_match_score():
    from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher

    inv = _invoice(10248, 560000)
    matcher = CourierOrderMatcher(invoice_query_fn=lambda: [inv])
    result = matcher.match_row({
        "normalized_order_number": "10248",
        "collected_amount": 560000,
        "customer_name": "محمد",
        "customer_phone": "07701234567",
    })
    assert result["score"] >= 75
    assert result["status"] == "matched"
    print("test_exact_order_match_score ok")


def test_amount_mismatch_hint():
    from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher

    inv = _invoice(10248, 500000)
    matcher = CourierOrderMatcher(invoice_query_fn=lambda: [inv])
    result = matcher.match_row({
        "normalized_order_number": "10248",
        "collected_amount": 560000,
    })
    assert "amount_mismatch_hint" in result.get("reasons", []) or result["status"] != "matched"
    print("test_amount_mismatch_hint ok")


def test_unknown_order_unmatched():
    from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher

    matcher = CourierOrderMatcher(invoice_query_fn=lambda: [])
    result = matcher.match_row({"normalized_order_number": "99999", "collected_amount": 1000})
    assert result["status"] == "unmatched"
    print("test_unknown_order_unmatched ok")


def test_barcode_with_one_spurious_digit_uses_supporting_evidence():
    from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher

    inv = _invoice(449, 145000, phone="07701234567")
    inv.barcode = "210785"
    matcher = CourierOrderMatcher(invoice_query_fn=lambda: [inv])
    result = matcher.match_row({
        "normalized_order_number": "2109785",
        "collected_amount": 145000,
        "customer_phone": "07701234567",
    })

    assert result["status"] == "matched"
    assert result["matched_invoice_id"] == 449
    assert "order_number_single_extra_digit" in result["reasons"]
    print("test_barcode_with_one_spurious_digit_uses_supporting_evidence ok")


def test_wrong_phone_prevents_shifted_barcode_from_winning():
    from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher

    wrong_barcode = _invoice(501, 500000, name="wrong customer", phone="07700000000")
    wrong_barcode.barcode = "210640"
    right_customer = _invoice(502, 195000, name="right customer", phone="07765380193")
    right_customer.barcode = "210635"
    matcher = CourierOrderMatcher(invoice_query_fn=lambda: [wrong_barcode, right_customer])
    result = matcher.match_row({
        "normalized_order_number": "210640",
        "collected_amount": 195000,
        "customer_phone": "07765380193",
        "customer_name": "right customer",
        "statement_date": None,
    })

    assert result["matched_invoice_id"] == 502
    assert result["status"] == "review"
    assert "phone_last8_match" in result["reasons"]
    print("test_wrong_phone_prevents_shifted_barcode_from_winning ok")


def test_secondary_customer_phone_supports_match():
    from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher

    inv = _invoice(
        503,
        139000,
        phone="07711111111",
        phone2="07760643750",
    )
    inv.barcode = "210642"
    matcher = CourierOrderMatcher(invoice_query_fn=lambda: [inv])
    result = matcher.match_row({
        "normalized_order_number": "2100642",
        "collected_amount": 139000,
        "customer_phone": "07760643750",
    })

    assert result["matched_invoice_id"] == 503
    assert result["status"] == "matched"
    assert "phone_last8_match" in result["reasons"]
    assert "phone_mismatch_hint" not in result["reasons"]


def test_partial_payment_matches_statement_against_remaining_balance():
    from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher

    inv = _invoice(
        508,
        314000,
        phone="07707040222",
        payment="جزئي",
        paid_amount=145000,
    )
    matcher = CourierOrderMatcher(invoice_query_fn=lambda: [inv])
    result = matcher.match_row({
        "normalized_order_number": "508",
        "collected_amount": 169000,
        "customer_phone": "07707040222",
    })

    assert result["status"] == "matched"
    assert result["matched_invoice_id"] == 508
    assert "amount_matches_remaining" in result["reasons"]
    assert result["invoice_snapshot"]["paid_amount"] == 145000
    assert result["invoice_snapshot"]["remaining_amount"] == 169000


def test_settled_order_with_zero_collection_matches_zero_balance():
    from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher

    inv = _invoice(
        509,
        169000,
        phone="07707040222",
        payment="مسدد",
        paid_amount=169000,
    )
    matcher = CourierOrderMatcher(invoice_query_fn=lambda: [inv])
    result = matcher.match_row({
        "normalized_order_number": "509",
        "collected_amount": 0,
        "customer_phone": "07707040222",
    })

    assert result["status"] == "matched"
    assert result["matched_invoice_id"] == 509
    assert "amount_matches_settled_balance" in result["reasons"]
    assert result["invoice_snapshot"]["remaining_amount"] == 0


def test_snapshot_verifies_paid_amount_against_account_allocations(monkeypatch):
    from modules.workspace.services.courier_settlement.invoice_snapshot_adapter import (
        InvoiceSnapshotAdapter,
    )

    inv = _invoice(
        510,
        169000,
        payment="مسدد",
        paid_amount=169000,
    )
    monkeypatch.setattr(
        InvoiceSnapshotAdapter,
        "get_payment_allocations",
        staticmethod(lambda _invoice: [
            {"account_name": "الصندوق", "amount": 100000},
            {"account_name": "المصرف", "amount": 69000},
        ]),
    )

    snapshot = InvoiceSnapshotAdapter.from_invoice(inv)

    assert snapshot["allocated_paid_amount"] == 169000
    assert snapshot["payment_verified_in_accounts"] is True


def test_second_shipping_barcode_matches_its_parent_order():
    from modules.workspace.services.courier_settlement.courier_order_matcher import CourierOrderMatcher

    inv = _invoice(508, 314000, phone="07707040222")
    inv.shipping_barcode = "508"
    inv.shipping_barcodes_json = json.dumps(["508", "210605"])
    matcher = CourierOrderMatcher(invoice_query_fn=lambda: [inv])

    result = matcher.match_row({
        "normalized_order_number": "210605",
        "collected_amount": 169000,
        "customer_phone": "07707040222",
    })

    assert result["status"] == "matched"
    assert result["matched_invoice_id"] == 508
    assert "order_number_exact" in result["reasons"]
    assert "piece_barcode_partial_amount" in result["reasons"]
    assert result["invoice_snapshot"]["shipping_barcodes"] == ["508", "210605"]


if __name__ == "__main__":
    test_exact_order_match_score()
    test_amount_mismatch_hint()
    test_unknown_order_unmatched()
    test_barcode_with_one_spurious_digit_uses_supporting_evidence()
    test_wrong_phone_prevents_shifted_barcode_from_winning()
    test_secondary_customer_phone_supports_match()
    print("All matcher tests passed.")
