from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
    CourierReadonlyAnalysisService,
)


def test_manual_exclusion_adjusts_declared_totals_once():
    summary = {
        "statement_totals": {
            "row_count": 34,
            "total_collected_amount": 1_000_000,
            "total_delivery_fees": 312_000,
            "expected_net_amount": 688_000,
        }
    }
    exclusions = [{
        "collected_amount": 25_000,
        "delivery_fee": 25_000,
        "net_amount": 0,
    }]

    adjusted = CourierReadonlyAnalysisService._apply_manual_exclusions_to_statement_totals(
        summary,
        exclusions,
    )
    totals = adjusted["statement_totals"]
    assert totals["row_count"] == 33
    assert totals["total_collected_amount"] == 975_000
    assert totals["total_delivery_fees"] == 287_000
    assert totals["expected_net_amount"] == 688_000

    adjusted_again = CourierReadonlyAnalysisService._apply_manual_exclusions_to_statement_totals(
        adjusted,
        exclusions,
    )
    assert adjusted_again["statement_totals"]["total_delivery_fees"] == 287_000


def test_non_manual_difference_remains_blocking_after_exclusion():
    summary = {
        "statement_totals": {
            "row_count": 3,
            "total_collected_amount": 300_000,
            "total_delivery_fees": 30_000,
            "expected_net_amount": 270_000,
        }
    }
    exclusions = [{
        "collected_amount": 100_000,
        "delivery_fee": 10_000,
        "net_amount": 90_000,
    }]
    CourierReadonlyAnalysisService._apply_manual_exclusions_to_statement_totals(
        summary,
        exclusions,
    )
    remaining_rows = [
        type("Row", (), {
            "collected_amount": 100_000,
            "delivery_fee": 10_000,
            "net_amount": 90_000,
        })(),
    ]

    issues = CourierReadonlyAnalysisService._statement_total_issues(
        summary["statement_totals"],
        remaining_rows,
    )
    assert issues
    assert all(issue["severity"] == "critical" for issue in issues)


def test_ocr_ghost_exclusion_keeps_original_printed_totals():
    summary = {
        "statement_totals": {
            "row_count": 2,
            "total_collected_amount": 300_000,
            "total_delivery_fees": 20_000,
            "expected_net_amount": 280_000,
        }
    }
    exclusions = [{
        "collected_amount": 6_000,
        "delivery_fee": 0,
        "net_amount": 6_000,
    }]
    rows = [
        type("Row", (), {
            "collected_amount": 150_000,
            "delivery_fee": 10_000,
            "net_amount": 140_000,
        })(),
        type("Row", (), {
            "collected_amount": 150_000,
            "delivery_fee": 10_000,
            "net_amount": 140_000,
        })(),
    ]

    result = CourierReadonlyAnalysisService._apply_manual_exclusions_to_statement_totals(
        summary,
        exclusions,
        rows,
    )

    assert result["statement_totals"]["total_collected_amount"] == 300_000
    assert result["statement_totals"]["manual_exclusion_reference"] == "original"


def test_real_row_exclusion_uses_deducted_printed_totals():
    summary = {
        "statement_totals": {
            "row_count": 3,
            "total_collected_amount": 306_000,
            "total_delivery_fees": 20_000,
            "expected_net_amount": 286_000,
        }
    }
    exclusions = [{
        "collected_amount": 6_000,
        "delivery_fee": 0,
        "net_amount": 6_000,
    }]
    rows = [
        type("Row", (), {
            "collected_amount": 150_000,
            "delivery_fee": 10_000,
            "net_amount": 140_000,
        })(),
        type("Row", (), {
            "collected_amount": 150_000,
            "delivery_fee": 10_000,
            "net_amount": 140_000,
        })(),
    ]

    result = CourierReadonlyAnalysisService._apply_manual_exclusions_to_statement_totals(
        summary,
        exclusions,
        rows,
    )

    assert result["statement_totals"]["total_collected_amount"] == 300_000
    assert result["statement_totals"]["manual_exclusion_reference"] == "deducted"


def test_repairs_net_amount_read_as_collection_when_all_evidence_agrees():
    class Row:
        id = "r1"
        row_index = 1
        normalized_order_number = "210618"
        raw_order_number = "210618"
        match_status = "matched"
        collected_amount = 189_000
        delivery_fee = 6_000
        net_amount = 183_000

        def __init__(self):
            self.snapshot = {
                "id": 1,
                "total": 195_000,
                "paid_amount": 0,
                "shipping_barcodes": ["210618"],
            }
            self.warnings = []

        def get_invoice_snapshot(self):
            return self.snapshot

        def set_invoice_snapshot(self, value):
            self.snapshot = value

        def get_warnings(self):
            return self.warnings

        def set_warnings(self, value):
            self.warnings = value

    row = Row()
    repairs = CourierReadonlyAnalysisService._repair_net_read_as_collection(
        [row],
        {
            "row_count": 1,
            "total_collected_amount": 195_000,
            "total_delivery_fees": 6_000,
            "expected_net_amount": 189_000,
        },
    )

    assert len(repairs) == 1
    assert row.collected_amount == 195_000
    assert row.net_amount == 189_000
    assert "AUTO_CORRECTED_NET_READ_AS_COLLECTION" in row.warnings


def test_repairs_two_missing_amounts_when_footer_and_matches_prove_both():
    class Row:
        match_status = "matched"

        def __init__(
            self,
            row_id,
            order_number,
            total,
            collected,
            fee,
            net,
        ):
            self.id = row_id
            self.row_index = int(row_id[-1])
            self.normalized_order_number = order_number
            self.raw_order_number = order_number
            self.collected_amount = collected
            self.delivery_fee = fee
            self.net_amount = net
            self.snapshot = {
                "id": self.row_index,
                "total": total,
                "paid_amount": 0,
                "delivery_fee": 6_000,
                "shipping_barcodes": [order_number],
            }
            self.warnings = []

        def get_invoice_snapshot(self):
            return self.snapshot

        def set_invoice_snapshot(self, value):
            self.snapshot = value

        def get_warnings(self):
            return self.warnings

        def set_warnings(self, value):
            self.warnings = value

    first = Row("r1", "210601", 195_000, None, 6_000, 189_000)
    second = Row("r2", "210602", 139_000, 139_000, None, 133_000)

    repairs = CourierReadonlyAnalysisService._repair_missing_amounts_from_matches(
        [first, second],
        {
            "row_count": 2,
            "total_collected_amount": 334_000,
            "total_delivery_fees": 12_000,
            "expected_net_amount": 322_000,
        },
    )

    assert len(repairs) == 2
    assert first.collected_amount == 195_000
    assert second.delivery_fee == 6_000
    assert all(
        "AUTO_REPAIRED_MISSING_AMOUNT_FROM_MATCH" in row.warnings
        for row in (first, second)
    )


def test_does_not_repair_missing_amount_when_it_worsens_printed_footer():
    class Row:
        id = "r1"
        row_index = 1
        normalized_order_number = "210601"
        raw_order_number = "210601"
        match_status = "matched"
        collected_amount = None
        delivery_fee = 6_000
        net_amount = 189_000

        def __init__(self):
            self.snapshot = {
                "id": 1,
                "total": 195_000,
                "paid_amount": 0,
                "delivery_fee": 6_000,
                "shipping_barcodes": ["210601"],
            }
            self.warnings = []

        def get_invoice_snapshot(self):
            return self.snapshot

        def set_invoice_snapshot(self, value):
            self.snapshot = value

        def get_warnings(self):
            return self.warnings

        def set_warnings(self, value):
            self.warnings = value

    row = Row()
    repairs = CourierReadonlyAnalysisService._repair_missing_amounts_from_matches(
        [row],
        {
            "row_count": 1,
            "total_collected_amount": 0,
            "total_delivery_fees": 6_000,
            "expected_net_amount": 189_000,
        },
    )

    assert repairs == []
    assert row.collected_amount is None


def test_repairs_blank_collection_as_fee_only_for_verified_paid_multi_barcode_order():
    class Row:
        match_status = "matched"

        def __init__(self, row_id, barcode, fee):
            self.id = row_id
            self.row_index = int(row_id[-1])
            self.normalized_order_number = barcode
            self.raw_order_number = barcode
            self.collected_amount = None
            self.delivery_fee = fee
            self.net_amount = None
            self.snapshot = {
                "id": 210611,
                "total": 659_000,
                "paid_amount": 659_000,
                "remaining_amount": 0,
                "payment_status": "مسدد",
                "payment_verified_in_accounts": True,
                "delivery_fee": fee,
                "shipping_barcodes": ["210611", "210584"],
            }
            self.warnings = []

        def get_invoice_snapshot(self):
            return self.snapshot

        def set_invoice_snapshot(self, value):
            self.snapshot = value

        def get_warnings(self):
            return self.warnings

        def set_warnings(self, value):
            self.warnings = value

    first = Row("r1", "210611", 6_000)
    second = Row("r2", "210584", 20_000)

    repairs = CourierReadonlyAnalysisService._repair_missing_amounts_from_matches(
        [first, second],
        {
            "row_count": 2,
            "total_collected_amount": 0,
            "total_delivery_fees": 26_000,
            "expected_net_amount": -26_000,
        },
    )

    assert len(repairs) == 2
    assert first.collected_amount == 0
    assert first.net_amount == -6_000
    assert second.collected_amount == 0
    assert second.net_amount == -20_000
    assert all(
        "AUTO_REPAIRED_MISSING_AMOUNT_FROM_MATCH" in row.warnings
        for row in (first, second)
    )
