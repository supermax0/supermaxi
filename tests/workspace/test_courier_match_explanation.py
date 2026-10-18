"""Human-readable courier matching explanations."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _explain(row):
    from modules.workspace.services.courier_settlement.courier_match_explanation_service import (
        CourierMatchExplanationService,
    )

    return CourierMatchExplanationService.explain(row)


def test_same_phone_and_amount_explains_wrong_order_number():
    result = _explain(
        {
            "match_status": "review",
            "normalized_order_number": "2100777",
            "customer_phone": "07734651190",
            "collected_amount": 145000,
            "match_reasons": [
                "phone_last8_match",
                "amount_matches",
                "date_within_range",
            ],
            "invoice_snapshot": {
                "id": 489,
                "shipping_barcode": "210771",
                "customer_phone": "07734651190",
                "total": 145000,
            },
        }
    )

    assert result["status_label"] == "تحتاج مراجعة"
    assert "الهاتف والمبلغ متطابقان" in result["message"]
    assert "2100777" in result["message"]
    assert result["candidate"]["order_number"] == "210771"


def test_shifted_row_explains_phone_and_amount_difference():
    result = _explain(
        {
            "match_status": "review",
            "normalized_order_number": "2100638",
            "customer_phone": "07718778305",
            "collected_amount": 150000,
            "match_reasons": [
                "order_number_single_extra_digit",
                "amount_mismatch_hint",
                "phone_mismatch_hint",
            ],
            "invoice_snapshot": {
                "id": 523,
                "shipping_barcode": "210638",
                "customer_phone": "07783306559",
                "total": 195000,
            },
        }
    )

    assert "الهاتف" in result["message"]
    assert "150,000" in result["message"]
    assert "195,000" in result["message"]
    assert "صف مجاور" in result["suggested_action"]


def test_unmatched_without_candidate_has_clear_next_step():
    result = _explain(
        {
            "match_status": "unmatched",
            "normalized_order_number": "999999",
            "match_reasons": [],
            "invoice_snapshot": None,
        }
    )

    assert result["status_label"] == "غير موجود بالنظام"
    assert "لم يُعثر" in result["message"]
    assert "صحّح رقم الطلب" in result["suggested_action"]


def test_secondary_phone_is_reported_as_matching():
    result = _explain(
        {
            "match_status": "matched",
            "normalized_order_number": "210642",
            "customer_phone": "07760643750",
            "collected_amount": 139000,
            "match_reasons": ["order_number_exact", "phone_last8_match", "amount_matches"],
            "invoice_snapshot": {
                "id": 503,
                "shipping_barcode": "210642",
                "customer_phone": "07711111111",
                "customer_phone2": "07760643750",
                "customer_phones": ["07711111111", "07760643750"],
                "total": 139000,
            },
        }
    )

    phone_check = next(item for item in result["checks"] if item["key"] == "phone")
    assert phone_check["state"] == "match"
    assert phone_check["system"] == "07760643750"
    assert result["candidate"]["customer_phones"] == [
        "07711111111",
        "07760643750",
    ]


def test_partial_payment_explains_paid_and_remaining_balance():
    result = _explain(
        {
            "match_status": "matched",
            "normalized_order_number": "508",
            "customer_phone": "07707040222",
            "collected_amount": 169000,
            "match_reasons": [
                "order_number_exact",
                "phone_last8_match",
                "amount_matches_remaining",
            ],
            "invoice_snapshot": {
                "id": 508,
                "order_number": "508",
                "customer_phone": "07707040222",
                "total": 314000,
                "paid_amount": 145000,
                "remaining_amount": 169000,
                "payment_status": "جزئي",
            },
        }
    )

    amount_check = next(item for item in result["checks"] if item["key"] == "amount")
    assert amount_check["label"] == "الرصيد المتبقي"
    assert amount_check["state"] == "match"
    assert result["candidate"]["paid_amount"] == 145000
    assert result["candidate"]["remaining_amount"] == 169000
    assert "المدفوع سابقاً" in result["message"]


def test_settled_zero_collection_is_explained_as_delivery_fee_only():
    result = _explain(
        {
            "match_status": "matched",
            "normalized_order_number": "509",
            "customer_phone": "07707040222",
            "collected_amount": 0,
            "delivery_fee": 10000,
            "match_reasons": [
                "order_number_exact",
                "phone_last8_match",
                "amount_matches_settled_balance",
            ],
            "invoice_snapshot": {
                "id": 509,
                "order_number": "509",
                "customer_phone": "07707040222",
                "total": 169000,
                "paid_amount": 169000,
                "remaining_amount": 0,
                "payment_status": "مسدد",
                "payment_verified_in_accounts": True,
                "payment_allocations": [
                    {"account_name": "الصندوق", "amount": 169000},
                ],
            },
        }
    )

    amount_check = next(item for item in result["checks"] if item["key"] == "amount")
    assert amount_check["label"] == "الرصيد المتبقي"
    assert amount_check["state"] == "match"
    assert result["candidate"]["payment_verified_in_accounts"] is True
    assert "أجور توصيل فقط" in result["message"]
    assert "لن تُضاف دفعة ثانية" in result["suggested_action"]


def test_explanation_shows_the_matching_secondary_shipping_barcode():
    result = _explain(
        {
            "match_status": "matched",
            "normalized_order_number": "210605",
            "customer_phone": "07707040222",
            "collected_amount": 169000,
            "delivery_fee": 10000,
            "match_reasons": [
                "order_number_exact",
                "phone_last8_match",
                "piece_barcode_partial_amount",
            ],
            "invoice_snapshot": {
                "id": 508,
                "shipping_barcode": "508",
                "shipping_barcodes": ["508", "210605"],
                "customer_phone": "07707040222",
                "total": 314000,
            },
        }
    )

    assert result["candidate"]["order_number"] == "210605"
    assert result["candidate"]["matched_shipping_barcode"] == "210605"
    assert result["candidate"]["shipping_barcodes"] == ["508", "210605"]
    assert result["candidate"]["piece_settlement"] is True
    assert result["candidate"]["remaining_after_piece"] == 145000
    assert "دفعة جزئية" in result["suggested_action"]
