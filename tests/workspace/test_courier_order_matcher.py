"""Courier order matcher tests — Phase 5."""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _invoice(id_, total, name="محمد", phone="07701234567", status="تم التسليم", payment="غير مسدد"):
    customer = SimpleNamespace(phone=phone)
    return SimpleNamespace(
        id=id_,
        customer_name=name,
        customer=customer,
        total=total,
        status=status,
        payment_status=payment,
        shipping_company_id=1,
        barcode=None,
        shipping_barcode=None,
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


if __name__ == "__main__":
    test_exact_order_match_score()
    test_amount_mismatch_hint()
    test_unknown_order_unmatched()
    print("All matcher tests passed.")
