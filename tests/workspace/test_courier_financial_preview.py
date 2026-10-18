"""Courier financial preview tests — Phase 5."""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_financial_preview_totals():
    from modules.workspace.services.courier_settlement.courier_financial_preview_service import (
        CourierFinancialPreviewService,
    )

    rows = [
        SimpleNamespace(
            id="r1", match_status="matched", collected_amount=560000, delivery_fee=10000,
            normalized_order_number="1", get_invoice_snapshot=lambda: {"total": 560000},
        ),
        SimpleNamespace(
            id="r2", match_status="unmatched", collected_amount=100000, delivery_fee=5000,
            normalized_order_number="2", get_invoice_snapshot=lambda: None,
        ),
    ]
    issues = []
    preview = CourierFinancialPreviewService.compute(rows, issues)
    assert preview["total_collected_amount"] == 660000
    assert preview["total_delivery_fees"] == 15000
    assert preview["expected_net_amount"] == 645000
    assert preview["safe_to_post_rows"] == 1
    print("test_financial_preview_totals ok")


def test_safe_to_post_excludes_blocked():
    from modules.workspace.services.courier_settlement.courier_financial_preview_service import (
        CourierFinancialPreviewService,
    )

    rows = [
        SimpleNamespace(
            id="r1", match_status="matched", collected_amount=100000, delivery_fee=0,
            normalized_order_number="1", get_invoice_snapshot=lambda: {"total": 100000},
        ),
        SimpleNamespace(
            id="r2", match_status="matched", collected_amount=200000, delivery_fee=0,
            normalized_order_number="2", get_invoice_snapshot=lambda: {"total": 200000},
        ),
    ]
    issues = [{"issue_type": "ORDER_ALREADY_SETTLED", "severity": "critical", "row_id": "r2"}]
    preview = CourierFinancialPreviewService.compute(rows, issues)
    assert preview["safe_to_post_rows"] == 1
    assert preview["blocked_rows"] >= 1
    print("test_safe_to_post_excludes_blocked ok")


def test_profit_preview_uses_invoice_revenue_cogs_and_statement_fee(monkeypatch):
    from modules.workspace.services.courier_settlement.courier_profit_preview_service import (
        CourierProfitPreviewService,
    )

    rows = [
        SimpleNamespace(
            id="r1",
            match_status="matched",
            matched_invoice_id=101,
            delivery_fee=10000,
        ),
        SimpleNamespace(
            id="r2",
            match_status="matched",
            matched_invoice_id=102,
            delivery_fee=15000,
        ),
        SimpleNamespace(
            id="r3",
            match_status="unmatched",
            matched_invoice_id=None,
            delivery_fee=5000,
        ),
    ]
    monkeypatch.setattr(
        CourierProfitPreviewService,
        "_invoice_financials",
        staticmethod(lambda ids: {
            101: {"revenue": 145000, "cogs": 90000, "item_count": 1},
            102: {"revenue": 100000, "cogs": 110000, "item_count": 1},
        }),
    )

    result = CourierProfitPreviewService.compute(rows)
    assert result["total_profit"] == 45000
    assert result["total_loss"] == 25000
    assert result["net_profit"] == 20000
    assert result["avg_profit"] == 10000
    assert result["eligible_rows"] == 2
    assert result["skipped_rows"] == 1
    print("test_profit_preview_uses_invoice_revenue_cogs_and_statement_fee ok")


if __name__ == "__main__":
    test_financial_preview_totals()
    test_safe_to_post_excludes_blocked()
    print("All financial preview tests passed.")
