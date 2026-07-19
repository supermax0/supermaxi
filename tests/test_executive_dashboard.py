"""Tests for executive dashboard helpers."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_get_executive_alerts_includes_href():
    from utils.executive_dashboard_data import get_executive_alerts

    alerts = get_executive_alerts(
        overdue_installments_count=2,
        overdue_installments_amount=150_000,
    )
    assert len(alerts) == 1
    assert alerts[0]["type"] == "credit_overdue"
    assert alerts[0]["href"] == "/customers/credit/"

    def _fake_overdue(**kwargs):
        return [{"severity": "critical"}]

    alerts = get_executive_alerts(overdue_orders_fn=_fake_overdue)
    assert len(alerts) == 1
    assert alerts[0]["type"] == "orders_overdue"
    assert alerts[0]["href"] == "/orders?status=ordered"


def test_get_credit_executive_summary_uses_unified_receivables_total():
    from unittest.mock import MagicMock, patch

    from utils.executive_dashboard_data import get_credit_executive_summary

    with patch("utils.executive_dashboard_data._invoices_for_range", return_value=[]), patch(
        "utils.executive_dashboard_data.CustomerInstallment"
    ) as installment_model:
        installment_model.query.all.return_value = []
        summary = get_credit_executive_summary(
            today=date(2026, 7, 11),
            collection_rate=55,
            receivables_total=9_500_000,
        )
    assert summary["receivables"] == 9_500_000
    assert summary["collection_rate"] == 55


def test_build_receivables_proxy_series_works_backwards():
    from utils.executive_dashboard_data import build_receivables_proxy_series

    proxy = build_receivables_proxy_series([100, 200, 50, 0, 0, 0, 300], 1_000_000)
    assert proxy[-1] == 1_000_000
    assert proxy[-2] == max(0, 1_000_000 - 300)
    assert len(proxy) == 7


def test_build_daily_net_position_series():
    from utils.executive_dashboard_data import build_daily_net_position_series

    result = build_daily_net_position_series(
        [100, 200, 300],
        [50, 60, 70],
        liabilities=40,
    )
    assert result == [110, 220, 330]
